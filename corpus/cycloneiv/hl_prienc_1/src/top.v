module top (
  input clk,
  output y
);
reg [31:0] stim0;
reg [3:0] pe1;
reg pv2;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) begin
  pv2 <= |{stim0[18], stim0[7], stim0[0], stim0[30], stim0[5], stim0[12], stim0[19], stim0[9], stim0[1], stim0[28], stim0[24], stim0[26], stim0[20], stim0[14], stim0[13], stim0[23]};
  casez ({stim0[18], stim0[7], stim0[0], stim0[30], stim0[5], stim0[12], stim0[19], stim0[9], stim0[1], stim0[28], stim0[24], stim0[26], stim0[20], stim0[14], stim0[13], stim0[23]})
    16'b???????????????1: pe1 <= 4'd0;
    16'b??????????????10: pe1 <= 4'd1;
    16'b?????????????100: pe1 <= 4'd2;
    16'b????????????1000: pe1 <= 4'd3;
    16'b???????????10000: pe1 <= 4'd4;
    16'b??????????100000: pe1 <= 4'd5;
    16'b?????????1000000: pe1 <= 4'd6;
    16'b????????10000000: pe1 <= 4'd7;
    16'b???????100000000: pe1 <= 4'd8;
    16'b??????1000000000: pe1 <= 4'd9;
    16'b?????10000000000: pe1 <= 4'd10;
    16'b????100000000000: pe1 <= 4'd11;
    16'b???1000000000000: pe1 <= 4'd12;
    16'b??10000000000000: pe1 <= 4'd13;
    16'b?100000000000000: pe1 <= 4'd14;
    16'b1000000000000000: pe1 <= 4'd15;
    default: pe1 <= 4'd0;
  endcase
end
always @(posedge clk) y_q <= (^pe1) ^ pv2;
assign y = y_q;
endmodule
